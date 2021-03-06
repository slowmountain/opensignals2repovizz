import os
from xml.dom import minidom
import re
import shutil
import zipfile
import h5py
import lxml.etree as ET


# TODOs:
# Add a good error when sampling rate is not extracted correctly (i.e. divide by zero warning)

# Dictionary used to add attributes to the XML nodes
extracting_rules={
    'Name': lambda hdf5, xml: hdf5.name.split('/')[-1] if re.match('([0-9A-F]{2}[:-]){5}([0-9A-F]{2})', hdf5.name.split('/')[-1]) is None else hdf5.attrs.get('device'),
    'Category': lambda hdf5, xml: extracting_rules['Name'](hdf5, xml).replace(":", "").upper(),
    'Expanded': lambda hdf5, xml: '1',
    '_Extra': lambda hdf5, xml: '' if isinstance(hdf5, h5py.highlevel.Group) else 'canvas=-1,color=0,selected=1',
    'DefaultPath': lambda hdf5, xml: '0',
    'EstimatedSampleRate': lambda hdf5, xml: '0.0',
    'FrameSize': lambda hdf5, xml: '',
    'BytesPerSample': lambda hdf5, xml: '',
    'NumChannels': lambda hdf5, xml: '',
    'NumSamples': lambda hdf5, xml: str(hdf5.len()),
    'ResampledFlag': lambda hdf5, xml: '-1',
    'SpecSampleRate': lambda hdf5, xml: '0.0',
    'FileType': lambda hdf5, xml: 'CSV',
    'MinVal': lambda hdf5, xml: "",
    'MaxVal': lambda hdf5, xml: ""
}

# Default anonymity preferences for OpenSignals users
anonymity_prefs={
    'channels': True,
    'comments': False,
    'date': False,
    'device': False,
    'device connection': False,
    'device name': False,
    'digital IO': False,
    'duration': True,
    'firmware version': True,
    'macaddress': False,
    'mode': True,
    'nsamples': True,
    'resolution': True,
    'sampling rate': True,
    'sync interval': True,
    'time': False,
}


def enumerate_siblings(father_node, child_node):
    """ Calculates the number of nodes on the same level that will have the same ID, and returns the final number to be
    appended (_0, _1 etc) """
    siblings = father_node.findall("./")
    sibling_counter = 0
    for node in siblings:
        if node.get('Category')[:4]==child_node.get('Category')[:4]:
            sibling_counter += 1
    return father_node.get('ID')+'_'+child_node.get('Category')[:4]+str(sibling_counter-1)


def create_generic_node(hdf5_node, xml_node):
    """ Creates a Generic node in the XML tree of the Repovizz datapack """
    new_node = ET.SubElement(xml_node, 'Generic')
    for id in ('Name', 'Category', 'Expanded', '_Extra'):
        new_node.set(id, extracting_rules[id](hdf5_node, xml_node))
    new_node.set('ID', enumerate_siblings(xml_node, new_node))
    return new_node


def create_metadata_node(hdf5_node, xml_node, parent_xml_node):
    """ Creates a Generic (METADATA) node in the XML tree of the Repovizz datapack """
    new_node = ET.SubElement(parent_xml_node, 'Generic')
    new_node.set('Category', 'METADATA')
    new_node.set('Name', 'HDF5 Attributes')
    for id in ('Expanded', '_Extra'):
        new_node.set(id, extracting_rules[id](hdf5_node, xml_node))
    new_node.set('ID', enumerate_siblings(parent_xml_node, new_node))
    for id in anonymity_prefs:
        if hdf5_node.attrs.get(id) is not None and anonymity_prefs[id] is True:
            # Add a Description node for each attribute
            new_desc_node = ET.SubElement(new_node, 'Description')
            new_desc_node.set('Category',id.upper())
            new_desc_node.set('Text',str(hdf5_node.attrs.get(id)))
            for id in ('Expanded', '_Extra'):
                new_desc_node.set(id, extracting_rules[id](hdf5_node, xml_node))
            new_desc_node.set('ID', enumerate_siblings(new_node, new_desc_node))
    return new_node


def create_description_node(hdf5_node, xml_node):
    """ Creates a Generic (METADATA) node in the XML tree of the Repovizz datapack """
    new_node = ET.SubElement(xml_node, 'Description')
    new_node.set('Category',hdf5_node.name.split('/')[-1].upper())
    new_node.set('Text',str(hdf5_node.value))
    for id in ('Expanded', '_Extra'):
        new_node.set(id, extracting_rules[id](hdf5_node, xml_node))
    new_node.set('ID', enumerate_siblings(xml_node, new_node))


def create_signal_node(hdf5_node, xml_node, sampling_rate, duration):
    """ Creates a Signal node in the XML tree of the Repovizz datapack """
    new_node = ET.SubElement(xml_node, 'Signal')
    for id in ('Name', 'Category', 'Expanded', '_Extra', 'DefaultPath', 'EstimatedSampleRate', 'FrameSize',
               'BytesPerSample', 'NumChannels', 'NumSamples', 'ResampledFlag', 'SpecSampleRate', 'FileType',
               'MinVal', 'MaxVal'):
        new_node.set(id, extracting_rules[id](hdf5_node, xml_node))
    new_node.set('ID', enumerate_siblings(xml_node, new_node))
    new_node.set('Filename',new_node.get('ID').lower()+'.csv')
    # Deduce the sampling rate from the original sampling rate, duration, and number of samples
    #  TODO: This samplerate calculation is quite crude, could be simplified by making stronger assumptions
    new_node.set('SampleRate', str(min(sampling_rate/[1.0,10.0,100.0,1000.0], key=lambda x:abs(x-hdf5_node.len()/duration))))
    return new_node


def write_signal_node_to_disk(hdf5_node, signal_node, sampling_rate, duration, directory):
    """ Writes a repovizz-style .csv file to disk with the contents of a Signal node """
    with open(os.path.join(directory, signal_node.get('ID').lower()+'.csv'), "w") as text_file:
        # Extract min and max values
        [minimum, maximum] = get_min_max_values(hdf5_node)
        # Write the contents of the HDF5 Dataset in a repovizz .csv file
        text_file.write('repovizz,framerate='+str(sampling_rate/round(sampling_rate/round(hdf5_node.len()/duration))) + ",minval=" + str(minimum) + ",maxval=" + str(maximum) + '\n')

        for value in hdf5_node.value:
            text_file.write(str(value[0])+',')


def get_min_max_values(hdf5_node):
    minimum = float('inf')
    maximum = -float('inf')

    for value in hdf5_node.value:
        if value[0] < minimum :
            minimum = value[0]

        if value[0] > maximum :
            maximum = value[0]

    if minimum == float('inf'):
        minimum = -1.0

    if maximum == -float('inf'):
        maximum = 1.0

    # repovizz assumes maxval > 0
    # and minval = 0 or minval = -maxval
    if maximum <= 0:
        if minimum < 0:
            maximum = -minimum
        else:  # min == 0 and max == 0
            minimum = -1.
            maximum = 1.
    elif minimum >= 0:
        minimum = 0.
    else:  # min < 0
        maximum = max(maximum, -minimum)
        minimum = -maximum

    return [float(minimum), float(maximum)]


def traverse_hdf5(hdf5_node, xml_node, sampling_rate, duration, directory):
    """ Recursively traverses the HDF5 tree, adding XML nodes and writing the contents of 'Dataset' nodes into .csv
    files using the repovizz-csv format. """
    if isinstance(hdf5_node, h5py.highlevel.Group):
        # Add a Generic node for each HDF5 Group (used as a container for other nodes)
        new_generic_node = create_generic_node(hdf5_node, xml_node)
        # Add a Generic node for HDF5 Group attributes (used as a METADATA container)
        new_metadata_node = create_metadata_node(hdf5_node, xml_node, new_generic_node)
        for children in hdf5_node:
            traverse_hdf5(hdf5_node[children], new_generic_node, sampling_rate, duration, directory)
    elif isinstance(hdf5_node, h5py.highlevel.Dataset):
        if hdf5_node.len() > 0:
            if hdf5_node.name.split('/')[-2].lower() == 'events':
                # Add a Description node for each Event
                # TODO Actually deal with event nodes...
                new_description_node = create_description_node(hdf5_node, xml_node)
            else:
                # Add a Signal node for each HDF5 Dataset
                new_signal_node = create_signal_node(hdf5_node, xml_node, sampling_rate, duration)
                # Write the contents of the Signal node to a repovizz-style .csv file
                write_signal_node_to_disk(hdf5_node, new_signal_node, sampling_rate, duration, directory)



def strtime_to_seconds(strtime):
    """ Returns the recording's duration (in seconds) as it is read from the hdf5 file's header """
    hours = 0
    minutes = 0
    split_time =re.split('(\d+H)*(\d+M)*(\d+S)', strtime.upper())
    if split_time[1] is not None:
        hours = int(split_time[1][:-1])

    if split_time[2] is not None:
        minutes = int(split_time[2][:-1])

    seconds = int(split_time[3][:-1])

    return 3600*hours+60*minutes+seconds


def prettify(elem):
    """ Prints JSON in a pretty way """
    rough_string = ET.tostring(elem)
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def zipdir(path, zip_handle):
    """ Zips an entire directory using zipfile """
    for root, dirs, files in os.walk(path):
        for file in files:
            zip_handle.write(os.path.join(root, file),file)


def process_recording(path):
    """ Takes an input .h5 file, converts it to a repovizz datapack and zips it """
    [input_directory, input_filename] = os.path.split(path)
    output_directory = os.path.join(input_directory,input_filename[:-3])
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    output_xml = os.path.join(output_directory,input_filename[:-2]+'xml')
    f = h5py.File(path, 'r')
    sampling_rate = f[list(enumerate(f))[0][1]].attrs.get('sampling rate')
    duration = strtime_to_seconds(f[list(enumerate(f))[0][1]].attrs.get('duration'))
    root = ET.Element('ROOT')
    root.set('ID', 'ROOT0')
    for device in enumerate(f):
        traverse_hdf5(f[device[1]], root, sampling_rate, duration, output_directory)

    # Delete all Generic nodes that do not contain Signal nodes
    for empty_nodes in root.xpath(".//Generic[not(.//Signal|.//Description)]"):
        empty_nodes.getparent().remove(empty_nodes)

    with open(output_xml, "w") as text_file:
        text_file.write(ET.tostring(root))

    # Zip the generated directory and then delete it
    zipf = zipfile.ZipFile(path[:-2]+'zip', 'w')
    zipdir(output_directory, zipf)
    zipf.close()
    shutil.rmtree('/'+output_directory)


if __name__ == '__main__':
    # used for internal testing
    #process_recording('/Users/panpap/Documents/opensignals/opensignals_file_2015-10-30_16-06-59.h5')
    #process_recording('/Users/panpap/Documents/opensignals/opensignals_file_2015-10-30_16-14-45.h5')
    process_recording('/Users/panpap/Documents/opensignals/opensignals_file_2015-11-04_11-19-39.h5')